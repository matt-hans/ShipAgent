/**
 * Address Book Section - Settings accordion section with inline CRUD.
 *
 * All contact management (search, add, edit, delete) happens directly
 * in this section within the settings flyout. No external modal needed.
 */

import * as React from 'react';
import { ChevronDown, BookUser, Plus, ArrowLeft, Search, Edit2, Trash2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAppState } from '@/hooks/useAppState';
import * as api from '@/lib/api';
import { ContactForm } from './ContactForm';
import type { Contact, ContactCreate, ContactUpdate } from '@/types/api';

interface AddressBookSectionProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function AddressBookSection({
  isOpen,
  onToggle,
}: AddressBookSectionProps) {
  const { contacts, refreshContacts } = useAppState();

  const [search, setSearch] = React.useState('');
  const [tagFilter, setTagFilter] = React.useState<string | null>(null);
  const [showForm, setShowForm] = React.useState(false);
  const [editingContact, setEditingContact] = React.useState<Contact | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [deleteConfirm, setDeleteConfirm] = React.useState<string | null>(null);
  const [isDeleting, setIsDeleting] = React.useState(false);

  /** Unique tags from all contacts. */
  const allTags = React.useMemo(() => {
    const tagSet = new Set<string>();
    contacts.forEach((c) => c.tags?.forEach((t) => tagSet.add(t)));
    return Array.from(tagSet).sort();
  }, [contacts]);

  /** Filter contacts by search and tag. */
  const filteredContacts = React.useMemo(() => {
    return contacts
      .filter((c) => {
        if (search) {
          const q = search.toLowerCase();
          const matchesSearch =
            c.handle.toLowerCase().includes(q) ||
            c.display_name.toLowerCase().includes(q) ||
            c.city.toLowerCase().includes(q) ||
            (c.state_province?.toLowerCase().includes(q) ?? false);
          if (!matchesSearch) return false;
        }
        if (tagFilter && !c.tags?.includes(tagFilter)) return false;
        return true;
      })
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
  }, [contacts, search, tagFilter]);

  /** Format a compact city/state one-liner. */
  const formatLocation = (contact: Contact): string => {
    const parts = [contact.city, contact.state_province].filter(Boolean);
    if (contact.country_code && contact.country_code !== 'US') {
      parts.push(contact.country_code);
    }
    return parts.join(', ');
  };

  const handleAddNew = () => {
    setEditingContact(null);
    setShowForm(true);
  };

  const handleEdit = (contact: Contact) => {
    setEditingContact(contact);
    setShowForm(true);
  };

  const handleDelete = async (contactId: string) => {
    setIsDeleting(true);
    try {
      await api.deleteContact(contactId);
      await refreshContacts();
      setDeleteConfirm(null);
    } catch (error) {
      console.error('Failed to delete contact:', error);
    } finally {
      setIsDeleting(false);
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
            className={`h-4 w-4 text-muted-foreground transition-transform ${isOpen ? 'rotate-180' : ''}`}
          />
        </div>
      </button>

      {isOpen && (
        <div className="settings-section-content space-y-3">
          {showForm ? (
            /* ── Form view ── */
            <div className="space-y-3">
              <button
                onClick={handleFormCancel}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <ArrowLeft className="h-3 w-3" />
                Back to contacts
              </button>
              <ContactForm
                contact={editingContact}
                onSubmit={handleFormSubmit}
                onCancel={handleFormCancel}
                isLoading={isLoading}
              />
            </div>
          ) : (
            /* ── List view ── */
            <>
              {/* Search + Add */}
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search contacts..."
                    className="pl-8 h-8 text-sm"
                  />
                </div>
                <Button
                  size="sm"
                  onClick={handleAddNew}
                  className="h-8 px-2.5"
                >
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </div>

              {/* Tag filter chips */}
              {allTags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  <button
                    onClick={() => setTagFilter(null)}
                    className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
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
                      className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
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
              {filteredContacts.length > 0 ? (
                <div className="max-h-80 overflow-y-auto space-y-2">
                  {filteredContacts.map((contact) => (
                    <div
                      key={contact.id}
                      className="flex items-start justify-between p-2 rounded border border-border bg-card hover:bg-muted/30 transition-colors"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <code className="text-xs font-mono text-rose-400">
                            @{contact.handle}
                          </code>
                          <span className="text-xs text-foreground truncate">
                            {contact.display_name}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5 truncate">
                          {formatLocation(contact)}
                        </p>
                        {contact.tags && contact.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1">
                            {contact.tags.slice(0, 3).map((t) => (
                              <span
                                key={t}
                                className="text-[9px] px-1.5 py-0 bg-muted rounded font-medium"
                              >
                                {t}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleEdit(contact)}
                        >
                          <Edit2 className="h-3 w-3" />
                        </Button>
                        {deleteConfirm === contact.id ? (
                          <div className="flex items-center gap-1">
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => handleDelete(contact.id)}
                              disabled={isDeleting}
                            >
                              Confirm
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setDeleteConfirm(null)}
                            >
                              <X className="h-3 w-3" />
                            </Button>
                          </div>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setDeleteConfirm(contact.id)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground text-center py-3">
                  {search || tagFilter ? 'No contacts match your filters.' : 'No contacts saved yet.'}
                </p>
              )}

              {/* Footer count */}
              {contacts.length > 0 && (
                <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground text-center pt-1">
                  {filteredContacts.length === contacts.length
                    ? `${contacts.length} saved contacts`
                    : `${filteredContacts.length} of ${contacts.length} matching`}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default AddressBookSection;
