/**
 * ContactAutocompleteService — Port of useContactAutocomplete.ts.
 *
 * Detects @handle tokens at the cursor position and returns filtered
 * candidates from the ContactsStore. Provides insertion helpers.
 *
 * Provided at component level (tied to RichChatInputComponent lifecycle).
 */

import { Injectable, inject, signal } from '@angular/core';
import { ContactsStore } from '@shipagent/shared-state';
import type { Contact } from '@shipagent/shared-types';

export interface ContactCandidate {
  handle: string;
  display_name: string;
  city: string;
  state_province: string | null;
}

@Injectable()
export class ContactAutocompleteService {
  private readonly contactsStore = inject(ContactsStore);

  // ---------------------------------------------------------------------------
  // State signals
  // ---------------------------------------------------------------------------

  readonly isOpen = signal(false);
  readonly selectedIndex = signal(0);
  readonly filteredContacts = signal<ContactCandidate[]>([]);
  readonly tokenStart = signal(0);
  readonly tokenEnd = signal(0);
  readonly query = signal('');

  // ---------------------------------------------------------------------------
  // Filter based on text + cursor position
  // ---------------------------------------------------------------------------

  /**
   * Update the autocomplete state based on the current text and cursor position.
   * Returns true if autocomplete is active.
   */
  filter(text: string, cursorPosition: number): boolean {
    const textBeforeCursor = text.slice(0, cursorPosition);
    const lastAtIndex = textBeforeCursor.lastIndexOf('@');

    if (lastAtIndex === -1) {
      this.close();
      return false;
    }

    const textAfterAt = textBeforeCursor.slice(lastAtIndex + 1);
    // Invalidate if space between @ and cursor
    if (textAfterAt.includes(' ')) {
      this.close();
      return false;
    }

    // Only trigger at start of word
    const charBeforeAt = lastAtIndex > 0 ? text[lastAtIndex - 1] : ' ';
    if (charBeforeAt !== ' ' && charBeforeAt !== '\n' && lastAtIndex !== 0) {
      this.close();
      return false;
    }

    const q = textAfterAt.toLowerCase();
    const contacts = this.contactsStore.contacts();
    const candidates: ContactCandidate[] = contacts
      .filter((c: Contact) => c.handle.toLowerCase().startsWith(q))
      .slice(0, 8)
      .map((c: Contact) => ({
        handle: c.handle,
        display_name: c.display_name,
        city: c.city,
        state_province: c.state_province,
      }));

    if (candidates.length === 0) {
      this.close();
      return false;
    }

    this.query.set(q);
    this.tokenStart.set(lastAtIndex);
    this.tokenEnd.set(cursorPosition);
    this.filteredContacts.set(candidates);
    this.isOpen.set(true);
    this.selectedIndex.set(0);
    return true;
  }

  /** Select a candidate and return the new text with the token replaced. */
  select(text: string, candidate: ContactCandidate): string {
    const start = this.tokenStart();
    const end = this.tokenEnd();
    const before = text.slice(0, start);
    const after = text.slice(end);
    return `${before}@${candidate.handle} ${after}`;
  }

  /** Move selection up or down. */
  moveSelection(direction: 1 | -1): void {
    const max = this.filteredContacts().length - 1;
    this.selectedIndex.update((i) => Math.max(0, Math.min(max, i + direction)));
  }

  /** Get the currently selected candidate. */
  getSelected(): ContactCandidate | null {
    return this.filteredContacts()[this.selectedIndex()] ?? null;
  }

  /** Close the autocomplete popover. */
  close(): void {
    this.isOpen.set(false);
    this.filteredContacts.set([]);
    this.selectedIndex.set(0);
  }
}
