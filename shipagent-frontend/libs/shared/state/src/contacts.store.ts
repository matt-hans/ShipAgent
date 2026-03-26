/**
 * ContactsStore — Address book state.
 *
 * Manages the list of saved contacts for @handle resolution and
 * address book UI display. Hydrated on app init and refreshed after mutations.
 */

import { signalStore, withState, withMethods, patchState } from '@ngrx/signals';
import type { Contact } from '@shipagent/shared-types';

export interface ContactsState {
  /** All contacts in the address book. */
  contacts: Contact[];
}

const initialState: ContactsState = {
  contacts: [],
};

export const ContactsStore = signalStore(
  { providedIn: 'root' },
  withState<ContactsState>(initialState),
  withMethods((store) => ({
    /** Replace all contacts (full refresh from API). */
    setContacts(contacts: Contact[]): void {
      patchState(store, { contacts });
    },

    /** Optimistically add a new contact to the list. */
    addContact(contact: Contact): void {
      patchState(store, (s) => ({ contacts: [...s.contacts, contact] }));
    },

    /** Optimistically update a contact by ID. */
    updateContact(id: string, updated: Partial<Contact>): void {
      patchState(store, (s) => ({
        contacts: s.contacts.map((c) => (c.id === id ? { ...c, ...updated } : c)),
      }));
    },

    /** Optimistically remove a contact by ID. */
    removeContact(id: string): void {
      patchState(store, (s) => ({
        contacts: s.contacts.filter((c) => c.id !== id),
      }));
    },
  })),
);
