/**
 * useContactAutocomplete - Autocomplete hook for @handle mentions.
 *
 * Triggered by @ prefix in text input. Returns filtered candidates
 * from AppState contacts for popover rendering.
 *
 * Selection inserts token + trailing space into the input.
 */

import { useMemo } from 'react';
import type { Contact } from '@/types/api';

export interface ContactCandidate {
  handle: string;
  display_name: string;
  city: string;
  state_province: string | null;
}

export interface UseContactAutocompleteOptions {
  /** Current input text */
  text: string;
  /** Current cursor position in the text */
  cursorPosition: number;
  /** All contacts from AppState */
  contacts: Contact[];
}

export interface ContactAutocompleteResult {
  /** Whether autocomplete should be shown */
  isActive: boolean;
  /** The partial @handle being typed (without @) */
  query: string;
  /** Filtered candidates matching the query */
  candidates: ContactCandidate[];
  /** Start position of the @ token in the text */
  tokenStart: number;
  /** End position of the @ token (cursor position) */
  tokenEnd: number;
}

/**
 * Detect if cursor is within an @handle token and return
 * matching candidates for autocomplete.
 */
export function useContactAutocomplete({
  text,
  cursorPosition,
  contacts,
}: UseContactAutocompleteOptions): ContactAutocompleteResult {
  return useMemo(() => {
    // Find @ before cursor
    const textBeforeCursor = text.slice(0, cursorPosition);

    // Find the last @ before cursor
    const lastAtIndex = textBeforeCursor.lastIndexOf('@');
    if (lastAtIndex === -1) {
      return { isActive: false, query: '', candidates: [], tokenStart: 0, tokenEnd: 0 };
    }

    // Check if there's a space between @ and cursor (invalidates the token)
    const textAfterAt = textBeforeCursor.slice(lastAtIndex + 1);
    if (textAfterAt.includes(' ')) {
      return { isActive: false, query: '', candidates: [], tokenStart: 0, tokenEnd: 0 };
    }

    // Check if there's a space immediately before @ (valid position)
    // Or @ is at the start of the text
    const charBeforeAt = lastAtIndex > 0 ? text[lastAtIndex - 1] : ' ';
    if (charBeforeAt !== ' ' && charBeforeAt !== '\n' && lastAtIndex !== 0) {
      return { isActive: false, query: '', candidates: [], tokenStart: 0, tokenEnd: 0 };
    }

    const query = textAfterAt.toLowerCase();
    const tokenStart = lastAtIndex;
    const tokenEnd = cursorPosition;

    // Filter contacts by handle prefix
    const candidates: ContactCandidate[] = contacts
      .filter((c) => c.handle.toLowerCase().startsWith(query))
      .slice(0, 8) // Limit to 8 candidates
      .map((c) => ({
        handle: c.handle,
        display_name: c.display_name,
        city: c.city,
        state_province: c.state_province,
      }));

    return {
      isActive: true,
      query,
      candidates,
      tokenStart,
      tokenEnd,
    };
  }, [text, cursorPosition, contacts]);
}

/**
 * Insert a selected contact handle into text.
 *
 * @param text - Original text
 * @param handle - Handle to insert (without @)
 * @param tokenStart - Start position of @ token
 * @param tokenEnd - End position (cursor position)
 * @returns New text with handle inserted + trailing space
 */
export function insertContactHandle(
  text: string,
  handle: string,
  tokenStart: number,
  tokenEnd: number
): string {
  const before = text.slice(0, tokenStart);
  const after = text.slice(tokenEnd);
  return `${before}@${handle} ${after}`;
}

export default useContactAutocomplete;
