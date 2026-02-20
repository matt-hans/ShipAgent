/**
 * useCommandAutocomplete - Autocomplete hook for /command expansion.
 *
 * Triggered by / prefix in text input. Returns filtered candidates
 * from AppState commands for popover rendering.
 *
 * Selection inserts token + trailing space into the input.
 */

import { useMemo } from 'react';
import type { CustomCommand } from '@/types/api';

export interface CommandCandidate {
  name: string;
  description: string | null;
  body: string;
}

export interface UseCommandAutocompleteOptions {
  /** Current input text */
  text: string;
  /** Current cursor position in the text */
  cursorPosition: number;
  /** All commands from AppState */
  commands: CustomCommand[];
}

export interface CommandAutocompleteResult {
  /** Whether autocomplete should be shown */
  isActive: boolean;
  /** The partial /command being typed (without /) */
  query: string;
  /** Filtered candidates matching the query */
  candidates: CommandCandidate[];
  /** Start position of the / token in the text */
  tokenStart: number;
  /** End position of the / token (cursor position) */
  tokenEnd: number;
}

/**
 * Detect if cursor is within a /command token and return
 * matching candidates for autocomplete.
 */
export function useCommandAutocomplete({
  text,
  cursorPosition,
  commands,
}: UseCommandAutocompleteOptions): CommandAutocompleteResult {
  return useMemo(() => {
    // Find / before cursor
    const textBeforeCursor = text.slice(0, cursorPosition);

    // Find the last / before cursor
    const lastSlashIndex = textBeforeCursor.lastIndexOf('/');
    if (lastSlashIndex === -1) {
      return { isActive: false, query: '', candidates: [], tokenStart: 0, tokenEnd: 0 };
    }

    // Check if there's a space between / and cursor (invalidates the token)
    const textAfterSlash = textBeforeCursor.slice(lastSlashIndex + 1);
    if (textAfterSlash.includes(' ')) {
      return { isActive: false, query: '', candidates: [], tokenStart: 0, tokenEnd: 0 };
    }

    // Check if there's a space immediately before / (valid position)
    // Or / is at the start of the text
    const charBeforeSlash = lastSlashIndex > 0 ? text[lastSlashIndex - 1] : ' ';
    if (charBeforeSlash !== ' ' && charBeforeSlash !== '\n' && lastSlashIndex !== 0) {
      return { isActive: false, query: '', candidates: [], tokenStart: 0, tokenEnd: 0 };
    }

    const query = textAfterSlash.toLowerCase();
    const tokenStart = lastSlashIndex;
    const tokenEnd = cursorPosition;

    // Filter commands by name prefix
    const candidates: CommandCandidate[] = commands
      .filter((c) => c.name.toLowerCase().startsWith(query))
      .slice(0, 8) // Limit to 8 candidates
      .map((c) => ({
        name: c.name,
        description: c.description,
        body: c.body,
      }));

    return {
      isActive: true,
      query,
      candidates,
      tokenStart,
      tokenEnd,
    };
  }, [text, cursorPosition, commands]);
}

/**
 * Insert a selected command name into text.
 *
 * @param text - Original text
 * @param name - Command name to insert (without /)
 * @param tokenStart - Start position of / token
 * @param tokenEnd - End position (cursor position)
 * @returns New text with command inserted + trailing space
 */
export function insertCommandName(
  text: string,
  name: string,
  tokenStart: number,
  tokenEnd: number
): string {
  const before = text.slice(0, tokenStart);
  const after = text.slice(tokenEnd);
  return `${before}/${name} ${after}`;
}

export default useCommandAutocomplete;
